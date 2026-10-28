// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Payroll period widget: how many export periods are open, locked and
 * exported, and the latest period's hours by pay type.
 */
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { Card, Badge } from '@/shared/ui';
import { getNumberLocale } from '@/stores/usePreferencesStore';
import { fetchPeriodDashboard } from './api';
import { payTypeLabel, statusLabel, statusVariant } from './PayrollPeriodsSection';

function hrs(v: string): string {
  const n = Number(v);
  if (!Number.isFinite(n)) return v;
  try {
    return new Intl.NumberFormat(getNumberLocale(), { maximumFractionDigits: 1 }).format(n);
  } catch {
    return n.toFixed(1);
  }
}

export function PayrollPeriodWidget({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const { data } = useQuery({
    queryKey: ['payroll', 'dashboard', projectId],
    queryFn: () => fetchPeriodDashboard(projectId),
    enabled: Boolean(projectId),
  });
  if (!data) return null;
  const types = Object.entries(data.latest_totals_by_type ?? {});
  return (
    <Card className="p-4" data-testid="payroll-period-widget">
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="text-sm font-semibold text-content-primary">
          {t('payroll.widget_title', { defaultValue: 'Pay periods' })}
        </h2>
        <Badge variant="blue" size="sm">
          {t('payroll.widget_open', { defaultValue: 'Open: {{n}}', n: data.by_status.open })}
        </Badge>
        <Badge variant="warning" size="sm">
          {t('payroll.widget_locked', { defaultValue: 'Locked: {{n}}', n: data.by_status.locked })}
        </Badge>
        <Badge variant="success" size="sm">
          {t('payroll.widget_exported', { defaultValue: 'Exported: {{n}}', n: data.by_status.exported })}
        </Badge>
      </div>
      {data.latest ? (
        <div className="mt-2 text-xs text-content-secondary">
          <span className="font-medium text-content-primary">{data.latest.label}</span>{' '}
          <Badge variant={statusVariant(data.latest.status)} size="sm">
            {statusLabel(data.latest.status, t)}
          </Badge>
          <div className="mt-1 flex flex-wrap gap-x-4 gap-y-0.5 tabular-nums">
            {types.map(([pt, v]) => (
              <span key={pt}>
                {payTypeLabel(pt, t)}: {hrs(v.hours)} h
              </span>
            ))}
          </div>
        </div>
      ) : (
        <p className="mt-2 text-xs text-content-tertiary">
          {t('payroll.widget_none', { defaultValue: 'No pay periods yet.' })}
        </p>
      )}
    </Card>
  );
}

export default PayrollPeriodWidget;
