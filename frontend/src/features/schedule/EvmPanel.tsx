// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
// EVM (earned value) panel - surfaces the existing schedule earned-value data
// (PV/EV/AC, BAC, SPI/CPI and the CPI-method forecast EAC/ETC/VAC) for one
// schedule at a data date. Reuses the shared StatCard/Card/Badge kit; all
// money is rendered through shared/lib/money.ts to honour the Decimal-as-string
// wire contract.

import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { TrendingUp, Wallet, Activity as ActivityIcon, Gauge, Target, AlertTriangle } from 'lucide-react';
import { Card, StatCard, Badge, SkeletonText, RecoveryCard } from '@/shared/ui';
import { formatCurrency, toNum } from '@/shared/lib/money';
import { scheduleApi } from './api';
import { classifyIndex, formatIndex, type EvmHealth } from './evm';

interface EvmPanelProps {
  scheduleId: string;
  /** Data date (ISO YYYY-MM-DD). Omitted -> backend uses today. */
  asOfDate?: string;
  /** Project ISO currency for money formatting (blank -> no symbol). */
  currency?: string;
}

/** Map an EVM health verdict to a Badge variant. */
function healthVariant(health: EvmHealth): 'success' | 'neutral' | 'error' {
  if (health === 'ahead') return 'success';
  if (health === 'behind') return 'error';
  return 'neutral';
}

export function EvmPanel({ scheduleId, asOfDate, currency }: EvmPanelProps) {
  const { t } = useTranslation();

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ['schedule', scheduleId, 'evm', asOfDate ?? 'today'],
    queryFn: () => scheduleApi.getEvmSummary(scheduleId, asOfDate),
    enabled: Boolean(scheduleId),
  });

  if (isLoading) {
    return (
      <Card padding="md" className="mt-4">
        <SkeletonText lines={4} />
      </Card>
    );
  }

  if (isError) {
    return (
      <div className="mt-4">
        <RecoveryCard error={error} onRetry={() => refetch()} />
      </div>
    );
  }

  if (!data) return null;

  // No cost data: EVM is undefined. Tell the user how to enable it rather than
  // rendering a wall of zeroes that looks like a broken project.
  if (!data.has_cost_data) {
    return (
      <Card padding="md" className="mt-4">
        <div className="flex items-start gap-3">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-surface-secondary text-content-tertiary">
            <Wallet size={16} />
          </div>
          <div>
            <h3 className="text-sm font-semibold text-content-primary">
              {t('schedule.evm.title', { defaultValue: 'Earned Value (EVM)' })}
            </h3>
            <p className="mt-1 max-w-xl text-xs text-content-secondary">
              {t('schedule.evm.no_cost_data', {
                defaultValue:
                  'This schedule is not cost-loaded yet. Generate activities from a BOQ, or set planned and actual cost on activities, to track PV, EV, AC and the SPI/CPI indices here.',
              })}
            </p>
          </div>
        </div>
      </Card>
    );
  }

  const spiHealth = classifyIndex(data.spi);
  const cpiHealth = classifyIndex(data.cpi);
  const sv = toNum(data.schedule_variance);
  const cv = toNum(data.cost_variance);
  const vac = data.variance_at_completion == null ? null : toNum(data.variance_at_completion);

  const indexLabel = (health: EvmHealth): string => {
    switch (health) {
      case 'ahead':
        return t('schedule.evm.health_ahead', { defaultValue: 'Ahead / under budget' });
      case 'behind':
        return t('schedule.evm.health_behind', { defaultValue: 'Behind / over budget' });
      case 'on_track':
        return t('schedule.evm.health_on_track', { defaultValue: 'On track' });
      default:
        return t('schedule.evm.health_unknown', { defaultValue: 'Not available' });
    }
  };

  return (
    <Card padding="md" className="mt-4">
      <div className="mb-3 flex items-center gap-2">
        <TrendingUp size={16} className="text-content-secondary" />
        <h3 className="text-sm font-semibold text-content-primary">
          {t('schedule.evm.title', { defaultValue: 'Earned Value (EVM)' })}
        </h3>
        <span className="text-2xs text-content-tertiary">
          {t('schedule.evm.as_of', { defaultValue: 'as of {{date}}', date: data.as_of_date })}
        </span>
      </div>

      {/* PV / EV / AC / BAC money KPIs */}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatCard
          label={t('schedule.evm.pv', { defaultValue: 'Planned Value (PV)' })}
          value={formatCurrency(data.planned_value, currency)}
          icon={ActivityIcon}
          tone="blue"
          sub={t('schedule.evm.pv_sub', { defaultValue: 'Budgeted work scheduled' })}
        />
        <StatCard
          label={t('schedule.evm.ev', { defaultValue: 'Earned Value (EV)' })}
          value={formatCurrency(data.earned_value, currency)}
          icon={TrendingUp}
          tone="success"
          sub={t('schedule.evm.ev_sub', { defaultValue: 'Budgeted work performed' })}
        />
        <StatCard
          label={t('schedule.evm.ac', { defaultValue: 'Actual Cost (AC)' })}
          value={formatCurrency(data.actual_cost, currency)}
          icon={Wallet}
          tone="warning"
          sub={t('schedule.evm.ac_sub', { defaultValue: 'Cost incurred to date' })}
        />
        <StatCard
          label={t('schedule.evm.bac', { defaultValue: 'Budget at Completion (BAC)' })}
          value={formatCurrency(data.budget_at_completion, currency)}
          icon={Target}
          sub={t('schedule.evm.bac_sub', { defaultValue: 'Total planned cost' })}
        />
      </div>

      {/* SPI / CPI performance indices */}
      <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div className="rounded-xl border border-border-light bg-surface-secondary/40 p-3">
          <div className="flex items-center justify-between">
            <span className="flex items-center gap-1.5 text-2xs font-semibold uppercase tracking-wide text-content-tertiary">
              <Gauge size={12} />
              {t('schedule.evm.spi', { defaultValue: 'Schedule Performance (SPI)' })}
            </span>
            <Badge variant={healthVariant(spiHealth)} size="sm">
              {indexLabel(spiHealth)}
            </Badge>
          </div>
          <p className="mt-1 text-2xl font-bold tabular-nums text-content-primary">
            {formatIndex(data.spi)}
          </p>
          <p className="mt-0.5 text-xs text-content-tertiary">
            {t('schedule.evm.sv', { defaultValue: 'Schedule variance (SV)' })}:{' '}
            <span className={sv >= 0 ? 'text-semantic-success' : 'text-semantic-error'}>
              {formatCurrency(data.schedule_variance, currency)}
            </span>
          </p>
        </div>

        <div className="rounded-xl border border-border-light bg-surface-secondary/40 p-3">
          <div className="flex items-center justify-between">
            <span className="flex items-center gap-1.5 text-2xs font-semibold uppercase tracking-wide text-content-tertiary">
              <Gauge size={12} />
              {t('schedule.evm.cpi', { defaultValue: 'Cost Performance (CPI)' })}
            </span>
            <Badge variant={healthVariant(cpiHealth)} size="sm">
              {indexLabel(cpiHealth)}
            </Badge>
          </div>
          <p className="mt-1 text-2xl font-bold tabular-nums text-content-primary">
            {formatIndex(data.cpi)}
          </p>
          <p className="mt-0.5 text-xs text-content-tertiary">
            {t('schedule.evm.cv', { defaultValue: 'Cost variance (CV)' })}:{' '}
            <span className={cv >= 0 ? 'text-semantic-success' : 'text-semantic-error'}>
              {formatCurrency(data.cost_variance, currency)}
            </span>
          </p>
        </div>
      </div>

      {/* Forecast block: EAC / ETC / VAC */}
      <div className="mt-3 rounded-xl border border-border-light bg-surface-secondary/40 p-3">
        <div className="mb-2 flex items-center gap-1.5">
          <Target size={13} className="text-content-secondary" />
          <span className="text-2xs font-semibold uppercase tracking-wide text-content-tertiary">
            {t('schedule.evm.forecast', { defaultValue: 'Forecast at completion (CPI method)' })}
          </span>
        </div>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <div>
            <p className="text-2xs text-content-tertiary">
              {t('schedule.evm.eac', { defaultValue: 'Estimate at Completion (EAC)' })}
            </p>
            <p className="text-lg font-semibold tabular-nums text-content-primary">
              {data.estimate_at_completion == null
                ? t('schedule.evm.not_available', { defaultValue: 'Not available' })
                : formatCurrency(data.estimate_at_completion, currency)}
            </p>
          </div>
          <div>
            <p className="text-2xs text-content-tertiary">
              {t('schedule.evm.etc', { defaultValue: 'Estimate to Complete (ETC)' })}
            </p>
            <p className="text-lg font-semibold tabular-nums text-content-primary">
              {data.estimate_to_complete == null
                ? t('schedule.evm.not_available', { defaultValue: 'Not available' })
                : formatCurrency(data.estimate_to_complete, currency)}
            </p>
          </div>
          <div>
            <p className="flex items-center gap-1 text-2xs text-content-tertiary">
              {t('schedule.evm.vac', { defaultValue: 'Variance at Completion (VAC)' })}
              {vac != null && vac < 0 && (
                <AlertTriangle size={11} className="text-semantic-error" aria-hidden />
              )}
            </p>
            <p
              className={`text-lg font-semibold tabular-nums ${
                vac == null
                  ? 'text-content-primary'
                  : vac >= 0
                    ? 'text-semantic-success'
                    : 'text-semantic-error'
              }`}
            >
              {vac == null
                ? t('schedule.evm.not_available', { defaultValue: 'Not available' })
                : formatCurrency(data.variance_at_completion, currency)}
            </p>
          </div>
        </div>
        <p className="mt-2 text-2xs text-content-tertiary">
          {t('schedule.evm.forecast_hint', {
            defaultValue:
              'EAC = BAC / CPI projects the final cost if current cost efficiency holds. A negative VAC signals a projected overrun.',
          })}
        </p>
      </div>
    </Card>
  );
}
