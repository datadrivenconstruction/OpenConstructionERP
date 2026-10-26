// DDC-CWICR-OE: DataDrivenConstruction​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * WipSummaryCard - compact dashboard widget: portfolio over-billing,
 * under-billing and profit fade per currency, linking to the WIP report.
 * Self-hides while loading, on error, and when the portfolio has no rows.
 */
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { ArrowRight } from 'lucide-react';
import { Card, CardContent, CardHeader } from '@/shared/ui';
import { formatCurrency } from '@/shared/lib/money';
import { fadeClass, fadeTone, useWipPortfolio } from './api';

export function WipSummaryCard() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { data, isLoading, isError } = useWipPortfolio();

  if (isLoading || isError || !data || data.rows.length === 0) return null;

  return (
    <Card className="h-full">
      <CardHeader
        title={t('wip_report.card_title', { defaultValue: 'WIP summary' })}
        subtitle={t('wip_report.card_subtitle', { defaultValue: 'Over- and under-billing across projects' })}
        action={
          <button
            type="button"
            onClick={() => navigate('/portfolio/wip')}
            className="inline-flex items-center gap-1.5 text-xs text-oe-blue hover:underline"
          >
            {t('wip_report.card_open', { defaultValue: 'Open WIP report' })}
            <ArrowRight size={11} />
          </button>
        }
      />
      <CardContent>
        <div className="space-y-3">
          {data.totals.map((tot) => (
            <div key={tot.currency} className="grid grid-cols-3 gap-2 text-xs" data-testid="wip-card-total">
              <div>
                <div className="text-2xs uppercase tracking-wide text-content-tertiary">{t('wip_report.col_over', { defaultValue: 'Over-billing' })}</div>
                <div className="tabular-nums font-semibold text-amber-700 dark:text-amber-400">{formatCurrency(tot.over_billing, tot.currency)}</div>
              </div>
              <div>
                <div className="text-2xs uppercase tracking-wide text-content-tertiary">{t('wip_report.col_under', { defaultValue: 'Under-billing' })}</div>
                <div className="tabular-nums font-semibold text-sky-700 dark:text-sky-400">{formatCurrency(tot.under_billing, tot.currency)}</div>
              </div>
              <div>
                <div className="text-2xs uppercase tracking-wide text-content-tertiary">{t('wip_report.col_fade', { defaultValue: 'Fade / gain' })}</div>
                <div className={`tabular-nums font-semibold ${fadeClass(fadeTone(tot.fade))}`}>{formatCurrency(tot.fade, tot.currency)}</div>
              </div>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

export default WipSummaryCard;
