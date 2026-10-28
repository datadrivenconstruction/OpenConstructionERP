// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import clsx from 'clsx';
import {
  Sparkles,
  TrendingDown,
  Wrench,
  PiggyBank,
  ChevronDown,
  ChevronUp,
  AlertTriangle,
} from 'lucide-react';
import { Card } from '@/shared/ui';
import { MoneyDisplay } from '@/shared/ui/MoneyDisplay';
import { getErrorMessage } from '@/shared/lib/api';
import { getFleetOptimization } from '../api';
import { fmtList, fmtPercent, fmtFixed } from '@/shared/lib/formatters';

/**
 * Fleet Intelligence card for the /equipment list page.
 *
 * Surfaces fleet-wide optimisation: how many units are underutilised vs the
 * target, the estimated monthly idle-cost saving opportunity and suggested
 * maintenance bundles. Computed on the fly from utilisation + open work orders.
 *
 * ``onSelect`` lets the parent open a unit's detail drawer when a row is
 * clicked, so an insight is one click from action.
 */
export function FleetOptimizationPanel({
  currency,
  onSelect,
}: {
  currency?: string;
  onSelect?: (equipmentId: string) => void;
}) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(false);

  const optQ = useQuery({
    queryKey: ['equipment', 'fleetOptimization'],
    queryFn: () => getFleetOptimization(),
  });

  if (optQ.isLoading) {
    return (
      <Card padding="md" className="animate-pulse">
        <div className="h-5 w-40 rounded bg-border-light" />
        <div className="mt-4 grid grid-cols-3 gap-3">
          <div className="h-14 rounded bg-border-light" />
          <div className="h-14 rounded bg-border-light" />
          <div className="h-14 rounded bg-border-light" />
        </div>
      </Card>
    );
  }

  if (optQ.isError || !optQ.data) {
    return (
      <Card padding="md">
        <p className="flex items-center gap-1.5 text-xs text-content-secondary">
          <AlertTriangle size={13} className="text-amber-500" />
          {optQ.error
            ? getErrorMessage(optQ.error)
            : t('equipment.fleet_intel.unavailable', {
                defaultValue: 'Fleet intelligence unavailable',
              })}
        </p>
      </Card>
    );
  }

  const o = optQ.data;
  const hasInsights =
    o.underutilized_count > 0 || o.maintenance_bundles.length > 0;

  return (
    <Card
      padding="md"
      className="border-oe-blue/20 bg-gradient-to-br from-oe-blue-subtle/10 to-transparent"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-1.5">
          <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-oe-blue-subtle text-oe-blue-text">
            <Sparkles size={14} />
          </div>
          <div>
            <h3 className="text-sm font-semibold text-content-primary">
              {t('equipment.fleet_intel.title', {
                defaultValue: 'Fleet Intelligence',
              })}
            </h3>
            <p className="text-2xs text-content-tertiary">
              {t('equipment.fleet_intel.subtitle', {
                defaultValue:
                  'Target utilisation {{target}}% over the last {{days}} days',
                target: fmtFixed(o.target_utilization_pct, 0),
                days: o.window_days,
              })}
            </p>
          </div>
        </div>
      </div>

      <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-3">
        <div className="rounded-lg border border-border-light bg-surface-primary px-3 py-2.5">
          <p className="flex items-center gap-1 text-2xs uppercase tracking-wide text-content-tertiary">
            <PiggyBank size={11} />
            {t('equipment.fleet_intel.savings', {
              defaultValue: 'Savings opportunity',
            })}
          </p>
          <p className="mt-1 text-lg font-semibold tabular-nums text-emerald-600 dark:text-emerald-400">
            <MoneyDisplay
              amount={o.estimated_monthly_savings}
              currency={currency || undefined}
            />
          </p>
          <p className="text-2xs text-content-tertiary">
            {t('equipment.fleet_intel.per_month', {
              defaultValue: 'est. per month',
            })}
          </p>
        </div>

        <div className="rounded-lg border border-border-light bg-surface-primary px-3 py-2.5">
          <p className="flex items-center gap-1 text-2xs uppercase tracking-wide text-content-tertiary">
            <TrendingDown size={11} />
            {t('equipment.fleet_intel.underutilized', {
              defaultValue: 'Underutilised units',
            })}
          </p>
          <p className="mt-1 text-lg font-semibold tabular-nums text-content-primary">
            {o.underutilized_count}
            <span className="ml-1 text-2xs font-normal text-content-tertiary">
              / {o.total_units}
            </span>
          </p>
        </div>

        <div className="rounded-lg border border-border-light bg-surface-primary px-3 py-2.5">
          <p className="flex items-center gap-1 text-2xs uppercase tracking-wide text-content-tertiary">
            <Wrench size={11} />
            {t('equipment.fleet_intel.service_bundles', {
              defaultValue: 'Service bundles',
            })}
          </p>
          <p className="mt-1 text-lg font-semibold tabular-nums text-content-primary">
            {o.maintenance_bundles.length}
          </p>
        </div>
      </div>

      {hasInsights && (
        <>
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            className="mt-3 inline-flex items-center gap-1 text-xs font-medium text-oe-blue hover:underline"
            aria-expanded={expanded}
          >
            {expanded
              ? t('equipment.fleet_intel.hide_details', {
                  defaultValue: 'Hide details',
                })
              : t('equipment.fleet_intel.show_details', {
                  defaultValue: 'Show details',
                })}
            {expanded ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
          </button>

          {expanded && (
            <div className="mt-3 space-y-4">
              {o.underutilized.length > 0 && (
                <div>
                  <h4 className="mb-1.5 text-2xs font-semibold uppercase tracking-wide text-content-tertiary">
                    {t('equipment.fleet_intel.idle_units_title', {
                      defaultValue: 'Idle units worth redeploying',
                    })}
                  </h4>
                  <div className="overflow-x-auto rounded-lg border border-border-light">
                    <table className="w-full text-xs">
                      <thead className="bg-surface-secondary text-content-tertiary uppercase tracking-wide">
                        <tr>
                          <th className="px-3 py-2 text-left">
                            {t('equipment.col_code', { defaultValue: 'Code' })}
                          </th>
                          <th className="px-3 py-2 text-left">
                            {t('equipment.col_name', { defaultValue: 'Name' })}
                          </th>
                          <th className="px-3 py-2 text-right">
                            {t('equipment.fleet_intel.utilization', {
                              defaultValue: 'Utilisation',
                            })}
                          </th>
                          <th className="px-3 py-2 text-right">
                            {t('equipment.fleet_intel.saving', {
                              defaultValue: 'Saving',
                            })}
                          </th>
                        </tr>
                      </thead>
                      <tbody>
                        {o.underutilized.map((u) => (
                          <tr
                            key={u.equipment_id}
                            onClick={() => onSelect?.(u.equipment_id)}
                            className={clsx(
                              'border-t border-border-light',
                              onSelect &&
                                'cursor-pointer hover:bg-surface-secondary',
                            )}
                          >
                            <td className="px-3 py-2 font-mono text-content-secondary">
                              {u.code}
                            </td>
                            <td className="px-3 py-2 truncate max-w-[180px]">
                              {u.name}
                            </td>
                            <td className="px-3 py-2 text-right tabular-nums text-amber-600 dark:text-amber-400">
                              {fmtPercent(u.utilization_pct, 0)}
                            </td>
                            <td className="px-3 py-2 text-right tabular-nums text-emerald-600 dark:text-emerald-400">
                              <MoneyDisplay
                                amount={u.estimated_monthly_saving}
                                currency={currency || undefined}
                              />
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {o.maintenance_bundles.length > 0 && (
                <div>
                  <h4 className="mb-1.5 text-2xs font-semibold uppercase tracking-wide text-content-tertiary">
                    {t('equipment.fleet_intel.bundles_title', {
                      defaultValue: 'Suggested service bundles',
                    })}
                  </h4>
                  <div className="space-y-2">
                    {o.maintenance_bundles.map((b, i) => (
                      <div
                        key={i}
                        className="flex items-center justify-between gap-3 rounded-lg border border-border-light bg-surface-primary px-3 py-2"
                      >
                        <div className="flex items-center gap-2">
                          <Wrench
                            size={13}
                            className="shrink-0 text-content-tertiary"
                          />
                          <span className="text-xs font-medium text-content-primary">
                            {b.label}
                          </span>
                        </div>
                        <div className="flex items-center gap-2">
                          <span className="text-2xs text-content-secondary truncate max-w-[200px]">
                            {fmtList(b.codes)}
                          </span>
                          <span className="rounded-full bg-oe-blue-subtle px-2 py-0.5 text-2xs font-medium text-oe-blue-text">
                            {t('equipment.fleet_intel.units', {
                              defaultValue: '{{count}} units',
                              count: b.unit_count,
                            })}
                          </span>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </>
      )}

      {!hasInsights && (
        <p className="mt-3 text-xs text-content-secondary">
          {t('equipment.fleet_intel.all_optimal', {
            defaultValue:
              'No optimisation opportunities right now - the fleet is running close to target.',
          })}
        </p>
      )}
    </Card>
  );
}
