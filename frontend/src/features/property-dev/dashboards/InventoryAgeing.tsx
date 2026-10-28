// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Inventory Ageing (task #140) — days-on-market histogram with a new
 * "Reserved, no contract" bucket for plots with an active Reservation
 * but no SalesContract yet.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { InventoryAgeingResponse } from '../api';
import { getInventoryAgeing } from '../api';
import { DashboardEmpty, DashboardError, DashboardSkeleton } from './_shared';

interface InventoryAgeingProps {
  developmentId: string;
}

export function InventoryAgeing({ developmentId }: InventoryAgeingProps) {
  const { t } = useTranslation();
  const [data, setData] = useState<InventoryAgeingResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);

  const [reloadKey, setReloadKey] = useState(0);
  const refetch = useCallback(() => setReloadKey((k) => k + 1), []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    getInventoryAgeing(developmentId)
      .then((r) => {
        if (!cancelled) setData(r);
      })
      .catch((e) => {
        if (!cancelled) setError(e?.message ?? 'Failed to load ageing');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [developmentId, reloadKey]);

  const max = useMemo(() => {
    if (!data) return 1;
    return Math.max(1, ...data.buckets.map((b) => b.count));
  }, [data]);

  if (loading) return <DashboardSkeleton variant="bars" rows={5} />;
  if (error)
    return (
      <DashboardError
        title={t('propdev.dashboards.ageing.error', {
          defaultValue: 'Could not load inventory ageing',
        })}
        message={error}
        onRetry={refetch}
      />
    );
  if (!data || data.total_unsold === 0)
    return (
      <DashboardEmpty
        title={t('propdev.dashboards.ageing.empty_title', {
          defaultValue: 'All inventory sold',
        })}
        description={t('propdev.dashboards.ageing.empty_desc', {
          defaultValue:
            'No plots in an unsold state - nothing to age out.',
        })}
      />
    );

  return (
    <div className="space-y-4">
      <div className="flex items-end justify-between">
        <div>
          <h3 className="text-sm font-semibold text-content-primary">
            {t('propdev.dashboards.ageing.title', {
              defaultValue: 'Inventory ageing',
            })}
          </h3>
          <p className="text-xs text-content-tertiary">
            {t('propdev.dashboards.ageing.subtitle', {
              defaultValue:
                'Days-on-market - {{total}} unsold • as of {{date}}',
              total: data.total_unsold,
              date: data.as_of,
            })}
          </p>
        </div>
      </div>

      <div className="space-y-2">
        {data.buckets.map((bucket) => {
          const pct = max <= 0 ? 0 : Math.min(100, (bucket.count / max) * 100);
          const isOpen = expanded === bucket.label;
          const isReservedBucket =
            bucket.label === 'Reserved, no contract' ||
            bucket.label.startsWith('Reserved');
          return (
            <div
              key={bucket.label}
              className="rounded-lg border border-divider/50"
            >
              <button
                type="button"
                aria-expanded={isOpen}
                onClick={() =>
                  setExpanded(isOpen ? null : bucket.label)
                }
                className="flex w-full items-center justify-between gap-3 px-3 py-2 text-left hover:bg-surface-secondary/60"
              >
                <div className="flex items-center gap-2 text-xs">
                  <span
                    className={
                      isReservedBucket
                        ? 'rounded bg-amber-100 px-1.5 py-0.5 font-medium text-amber-800'
                        : 'rounded bg-surface-secondary px-1.5 py-0.5 font-medium text-content-secondary'
                    }
                  >
                    {bucket.label}
                  </span>
                  <span className="text-content-tertiary">
                    {t('propdev.dashboards.ageing.count', {
                      defaultValue: '{{count}} plots',
                      count: bucket.count,
                    })}
                  </span>
                </div>
                <div
                  className="relative h-3 w-40 overflow-hidden rounded-full bg-surface-secondary"
                  role="progressbar"
                  aria-valuenow={Math.round(pct)}
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-label={bucket.label}
                >
                  <span
                    className={
                      isReservedBucket
                        ? 'absolute inset-y-0 left-0 rounded-full bg-amber-500'
                        : 'absolute inset-y-0 left-0 rounded-full bg-oe-blue'
                    }
                    style={{ width: `${pct}%` }}
                  />
                </div>
              </button>
              {isOpen && bucket.plots.length > 0 && (
                <div className="border-t border-divider/40 px-3 py-2">
                  <ul className="grid grid-cols-1 gap-1 text-xs sm:grid-cols-2 md:grid-cols-3">
                    {bucket.plots.map((p) => (
                      <li
                        key={p.plot_id}
                        className="flex items-center justify-between rounded bg-surface-secondary/40 px-2 py-1"
                      >
                        <span className="font-medium">{p.plot_number}</span>
                        <span className="text-content-tertiary">
                          {p.days_on_market}d • {p.status}
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
