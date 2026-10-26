// DDC-CWICR-OE: DataDrivenConstruction​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
// Portfolio cash-flow widget: per currency the peak funding requirement and
// month, the closing position, the projects that go negative (linked to their
// cost model) and the projects that have no forecast yet. Currencies are never
// summed together. Money is a Decimal-encoded string and is only formatted.

import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { Download, TrendingDown } from 'lucide-react';

import { Badge, Button, Card, Skeleton } from '@/shared/ui';
import { formatCurrency } from '@/shared/lib/money';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { cashflowForecastApi } from '@/features/costmodel/cashflowForecastApi';

export function PortfolioCashFlowWidget() {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const setActiveProject = useProjectContextStore((s) => s.setActiveProject);
  const [exporting, setExporting] = useState(false);

  const { data, isLoading, error } = useQuery({
    queryKey: ['portfolio', 'cashflow-forecast'],
    queryFn: () => cashflowForecastApi.getPortfolioForecast(),
    retry: false,
  });

  const onExport = async () => {
    setExporting(true);
    try {
      await cashflowForecastApi.exportPortfolio(undefined, 'portfolio-cashflow-forecast.xlsx');
    } catch (err) {
      addToast({
        type: 'error',
        title: t('portfolio.cf_export_failed', { defaultValue: 'Could not create the Excel file' }),
        message: getErrorMessage(err),
      });
    } finally {
      setExporting(false);
    }
  };

  const withoutForecast = data?.projects_without_forecast ?? [];

  return (
    <Card padding="md" data-testid="portfolio-cashflow-widget">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <TrendingDown size={16} className="text-content-secondary" />
          <h3 className="text-sm font-semibold text-content-primary">
            {t('portfolio.cf_title', { defaultValue: 'Portfolio cash flow' })}
          </h3>
        </div>
        <Button
          variant="secondary"
          size="sm"
          icon={<Download size={14} />}
          loading={exporting}
          disabled={!data || data.currencies.length === 0}
          onClick={onExport}
        >
          {t('portfolio.cf_export', { defaultValue: 'Export to Excel' })}
        </Button>
      </div>

      {isLoading ? (
        <Skeleton height={96} className="mt-3 w-full" rounded="lg" />
      ) : error ? (
        <p className="mt-3 text-sm text-semantic-error">
          {t('portfolio.cf_load_failed', { defaultValue: 'Could not load the portfolio cash flow' })}
          {': '}
          {getErrorMessage(error)}
        </p>
      ) : (
        <div className="mt-3 space-y-3">
          {(data?.currencies ?? []).length === 0 && (
            <p className="text-sm text-content-tertiary">
              {t('portfolio.cf_empty', { defaultValue: 'No project has cash-flow inputs yet.' })}
            </p>
          )}
          {(data?.currencies ?? []).map((c) => {
            const negatives = c.projects.filter((p) => p.negative);
            return (
              <div
                key={c.currency}
                data-testid={`portfolio-cf-${c.currency}`}
                className="rounded-lg border border-border-light p-3"
              >
                <div className="flex flex-wrap items-baseline gap-x-6 gap-y-1">
                  <span className="text-sm font-semibold">{c.currency}</span>
                  <span className="text-xs text-content-secondary">
                    {t('portfolio.cf_peak', { defaultValue: 'Peak funding' })}{': '}
                    {c.peak_funding ? (
                      <span className="font-semibold tabular-nums text-semantic-error">
                        {formatCurrency(c.peak_funding.amount, c.currency)}{' '}
                        <span className="font-normal text-content-tertiary">({c.peak_funding.period})</span>
                      </span>
                    ) : (
                      <span className="text-content-tertiary">
                        {t('portfolio.cf_none', { defaultValue: 'none' })}
                      </span>
                    )}
                  </span>
                  <span className="text-xs text-content-secondary">
                    {t('portfolio.cf_closing', { defaultValue: 'Closing position' })}{': '}
                    <span className="font-semibold tabular-nums">
                      {formatCurrency(c.closing_position, c.currency)}
                    </span>
                  </span>
                </div>
                {negatives.length > 0 && (
                  <div className="mt-2">
                    <div className="text-xs text-content-secondary">
                      {t('portfolio.cf_negative', { defaultValue: 'Projects going negative' })}{' '}
                      <Badge variant="error" size="sm">
                        {negatives.length}
                      </Badge>
                    </div>
                    <ul className="mt-1 space-y-0.5 text-sm">
                      {negatives.map((p) => (
                        <li key={p.project_id} className="flex justify-between gap-3">
                          <Link
                            to="/5d"
                            onClick={() => setActiveProject(p.project_id, p.project_name)}
                            className="font-medium text-oe-blue-text hover:underline"
                          >
                            {p.project_name}
                          </Link>
                          <span className="tabular-nums text-semantic-error">
                            {formatCurrency(p.closing_position, c.currency)}
                          </span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            );
          })}
          {withoutForecast.length > 0 && (
            <div className="text-xs text-content-secondary" data-testid="portfolio-cf-missing">
              {t('portfolio.cf_without_forecast', { defaultValue: 'Projects without a forecast' })}
              {': '}
              {withoutForecast.map((p, i) => (
                <span key={p.project_id}>
                  {i > 0 && ', '}
                  <Link
                    to="/5d"
                    onClick={() => setActiveProject(p.project_id, p.project_name)}
                    className="text-oe-blue-text hover:underline"
                  >
                    {p.project_name}
                  </Link>
                </span>
              ))}
            </div>
          )}
        </div>
      )}
    </Card>
  );
}

export default PortfolioCashFlowWidget;
