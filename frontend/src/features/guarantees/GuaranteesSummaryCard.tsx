// DDC-CWICR-OE: DataDrivenConstruction​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * GuaranteesSummaryCard - compact project dashboard widget: live guarantees,
 * those expiring within 60 days, expired ones and the live total per currency.
 * Self-hides without an active project, while loading, on error, and when the
 * project has no guarantees at all.
 */
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { ArrowRight } from 'lucide-react';
import { Card, CardContent, CardHeader } from '@/shared/ui';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { formatCurrency } from '@/shared/lib/money';
import { getNumberLocale } from '@/stores/usePreferencesStore';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { KpiStrip } from '@/features/dashboard/KpiStrip';
import { useGuaranteeSummary } from './api';

export function GuaranteesSummaryCard() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const projectId = useProjectContextStore((s) => s.activeProjectId) ?? '';
  const { data, isLoading, isError } = useGuaranteeSummary(projectId);

  if (!projectId || isLoading || isError || !data) return null;
  if (data.live_count + data.expiring_count + data.expired_count === 0) return null;

  const nf = new Intl.NumberFormat(getNumberLocale());
  return (
    <Card className="h-full">
      <CardHeader
        title={t('guarantees.card_title', { defaultValue: 'Guarantees' })}
        subtitle={t('guarantees.card_subtitle', { defaultValue: 'Live bank guarantees and bonds' })}
        action={
          <button
            type="button"
            onClick={() => navigate(`/projects/${projectId}/guarantees`)}
            className="inline-flex items-center gap-1.5 text-xs text-oe-blue hover:underline"
          >
            {t('guarantees.card_open', { defaultValue: 'Open guarantees' })}
            <ArrowRight size={11} />
          </button>
        }
      />
      <CardContent>
        <KpiStrip
          stats={[
            { label: t('guarantees.card_live', { defaultValue: 'Live' }), value: nf.format(data.live_count) },
            {
              label: t('guarantees.card_expiring', { defaultValue: 'Expiring soon' }),
              value: nf.format(data.expiring_count),
              tone: data.expiring_count > 0 ? 'text-amber-600' : 'text-content-secondary',
            },
            {
              label: t('guarantees.card_expired', { defaultValue: 'Expired' }),
              value: nf.format(data.expired_count),
              tone: data.expired_count > 0 ? 'text-rose-600' : 'text-content-secondary',
            },
          ]}
        />
        <div className="mt-3 space-y-0.5 text-xs text-content-secondary">
          {data.totals.map((tot) => (
            <div key={tot.currency} className="tabular-nums">{formatCurrency(tot.amount, tot.currency)}</div>
          ))}
          {data.next_expiry && (
            <div className="text-content-tertiary">
              {t('guarantees.card_next_expiry', { defaultValue: 'Next expiry' })}: <DateDisplay value={data.next_expiry} />
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

export default GuaranteesSummaryCard;
